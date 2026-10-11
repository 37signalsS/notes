# Выбор редакции GitLab для production

**Актуально для:** GitLab 17.x–19.x

## Определения

* **GitLab CE (Community Edition)** — бесплатная open-source версия GitLab для self-hosted развёртывания с базовым набором функций. Доступна под лицензией MIT.
 * **GitLab EE (Enterprise Edition)** — коммерческая версия GitLab с расширенными функциями для enterprise. Распространяется по подписке на тарифы Premium и Ultimate. На GitLab.com также доступен бесплатный тариф Free с ограничением до 5 пользователей на приватный namespace.
* **GitLab Self-Managed** — версия GitLab, развёртываемая на собственной инфраструктуре (on-premise).
* **GitLab SaaS** — облачная версия GitLab.com с managed инфраструктурой.
* **License (Лицензия)** — разрешение на использование GitLab EE. Типы: Free, Premium, Ultimate.
* **Seat (Место)** — единица учёта пользователей в лицензии GitLab EE.
* **TCO (Total Cost of Ownership)** — совокупная стоимость владения GitLab, включая лицензии, инфраструктуру и эксплуатацию.
* **Compliance (Комплаенс)** — набор функций для обеспечения соответствия требованиям регуляторов (PCI DSS, SOC 2, ISO 27001).

## Основные концепции

### Сравнение редакций

| Функция | GitLab CE | GitLab Free | GitLab EE Premium | GitLab EE Ultimate |
|:---|:---|:---|:---|:---|
| **Цена** | Бесплатно | Бесплатно (до 5 users) | $29/user/month | $99/user/month |
| **CI/CD** | Да | Да | Да | Да |
| **Container Registry** | Да | Да | Да | Да |
| **GitHub/GitLab mirroring** | Нет | Да | Да | Да |
| **Merge Request approvals** | Базовые | Базовые | Расширенные | Расширенные |
| **Code owners** | Нет | Да | Да | Да |
| **Multiple project templates** | Ограничено | Да | Да | Да |
| **Roadmaps** | Нет | Нет | Да | Да |
| **Agile portfolio management** | Нет | Нет | Да | Да |
| **Security Dashboard** | Нет | Нет | Да | Да |
| **Dependency scanning** | Нет | Нет | Да | Да |
| **Container scanning** | Нет | Нет | Да | Да |
| **Static Application Security Testing (SAST)** | Нет | Нет | Да | Да |
| **Dynamic Application Security Testing (DAST)** | Нет | Нет | Да | Да |
| **License Compliance** | Нет | Нет | Да | Да |
| **Vulnerability Management** | Нет | Нет | Да | Да |
| **Audit events** | Ограничено | 7 дней | 6 месяцев | Неограничено |
| **Geo (Disaster Recovery)** | Нет | Нет | Да | Да |
| **High Availability (HA)** | Ограничено | Нет | Да | Да |
| **Service Desk** | Нет | Нет | Да | Да |
| **Advanced CI/CD (include, rules, DAG)** | Да | Да | Да | Да |
| **CI/CD for external users** | Нет | Да | Да | Да |
| **Smartcard authentication** | Нет | Нет | Да | Да |
| **LDAP group sync** | Нет | Нет | Да | Да |
| **SAML SSO** | Ограничено | Да | Да | Да |
| **SCIM provisioning** | Нет | Нет | Да | Да |
| **Support** | Community | Community | Standard | Premium |

### CI/CD-специфичный разбор по редакциям

| CI/CD функция | CE | GitLab Free | EE Premium | EE Ultimate |
|:---|:---|:---|:---|:---|
| **Basic pipelines (stages, jobs)** | Да | Да | Да | Да |
| **Artifacts / Cache** | Да | Да | Да | Да |
| **Docker-in-Docker** | Да | Да | Да | Да |
| **Kubernetes executor** | Да | Да | Да | Да |
| **Matrix builds** | Да | Да | Да | Да |
| **Workflow rules / DAG** | Да | Да | Да | Да |
| **CI/CD Components** | Да | Да | Да | Да |
| **Reusable pipelines** | Да | Да | Да | Да |
| **Pipeline triggers** | Да | Да | Да | Да |
| **Scheduled pipelines** | Да | Да | Да | Да |
| **Merge Request pipelines** | Да | Да | Да | Да |
| **Review apps** | Да | Да | Да | Да |
| **Protected environments** | Да | Да | Да | Да |
| **Manual approvals** | Да | Да | Да | Да |
| **Container Registry** | Да | Да | Да | Да |
| **Package Registry** | Да | Да | Да | Да |
| **Dependency Proxy** | Да | Да | Да | Да |
| **GitLab Pages** | Да | Да | Да | Да |
| **CI_JOB_TOKEN** | Да | Да | Да | Да |
| **CI_JOB_TOKEN scope/allowlist** | Нет | Да | Да | Да |
| **spec:inputs (Pipeline Inputs)** | Нет | Да | Да | Да |
| **Pipeline execution policies** | Нет | Нет | Нет | Да |
| **Merge request approval rules** | Базовые | Базовые | Расширенные | Расширенные |
| **Compliance pipelines** | Нет | Нет | Нет | Да |
| **Audit events (CI/CD)** | Ограничено | 7 дней | 6 месяцев | Неограничено |
| **Security scanning (SAST/DAST/Secret)** | Нет | Нет | Да | Да |
| **Dependency scanning** | Нет | Нет | Да | Да |
| **Container scanning** | Нет | Нет | Да | Да |
| **License scanning** | Нет | Нет | Да | Да |
| **Vulnerability management** | Нет | Нет | Да | Да |
| **DORA metrics** | Нет | Нет | Да | Да |
| **Advanced observability** | Нет | Нет | Да | Да |
| **Geo (read-only mirrors)** | Нет | Нет | Да | Да |
| **High Availability (HA)** | Ограничено | Нет | Да | Да |
| **Failover promotion** | Нет | Нет | Нет | Да |

### Когда выбирать Ultimate для CI/CD

* **Pipeline Execution Policies** — принудительное внедрение security scanning на уровне группы/инстанса (Ultimate-only).
* **Compliance pipelines** — audit-ready пайплайны с mandated approval steps.
* **Unlimited audit events** — для регуляторных требований (PCI DSS, SOC 2, ISO 27001).
* **Geo** — disaster recovery и read-only зеркала для глобальных команд (Premium+, но advanced DR — Ultimate).
* **Advanced approval rules** — multi-level, group-level, compliance-managed approvals.
* **Vulnerability management** — centralized dashboard с triage workflow.

### Когда Premium достаточно для CI/CD

* **Security scanning** — SAST/DAST/Dependency/Container/License scanning (доступны с Premium).
* **Geo** — read-only зеркала для DR и ускорения Git-операций.
* **Extended audit events** — 6 месяцев хранения (обычно достаточно для compliance).
* **LDAP group sync** — enterprise authentication.
* **Priority support** — business hours.

### Критерии выбора для CI/CD команд

| Сценарий | Рекомендация | Обоснование |
|:---|:---|:---|
| Startup / PoC | GitLab CE | Бесплатно, базовый CI/CD |
| Small team, no compliance | GitLab CE / SaaS Free | Достаточно basic pipelines |
| Growing team, need security | GitLab EE Premium | Security scanning, extended approvals |
| Enterprise, strict compliance | GitLab EE Ultimate | Pipeline execution policies, compliance |
| Air-gapped / on-prem | GitLab EE Premium/Ultimate | Geo, HA, LDAP |
| Cost-sensitive | GitLab CE + external tools | Замена built-in security на Snyk/Trivy |

### Факторы выбора

| Фактор | CE | EE Premium | EE Ultimate |
|:---|:---|:---|:---|
| **Бюджет** | $0 | $29/user/month | $99/user/month |
| **Команда** | < 10 человек | 10–100 человек | 100+ человек |
| **Безопасность** | Базовая | Продвинутая | Enterprise-grade |
| **Compliance** | Нет | SOC 2 | PCI DSS, ISO 27001 |
| **Поддержка** | Community | Standard (business hours) | Premium (24/7) |
| **Сложность инфраструктуры** | Single Node | Distributed | Geo + Sharding |

## Практические сценарии

### Сценарий 1: Start-up / Small Team (< 10 users)

**Рекомендация:** GitLab CE или GitLab SaaS Free

```bash
# GitLab CE (self-hosted)
# - Бесплатно, открытый исходный код
# - Полный CI/CD функционал
# - Container Registry
# - Подходит для небольших команд

# Минимальные требования
CPU: 4 vCPU
RAM: 16 GB
Disk: 200 GB SSD
```

**Обоснование:**
* Нет затрат на лицензии.
* Все необходимые функции CI/CD доступны.
* Простота администрирования.

### Сценарий 2: Growing Team (10–100 users)

**Рекомендация:** GitLab EE Premium или GitLab CE + отдельные инструменты

```bash
# GitLab EE Premium (self-hosted)
# - Расширенные MR approvals
# - Security Dashboard
# - Dependency scanning
# - Geo (DR)
# - LDAP group sync

# Рекомендуемые требования
CPU: 8+ vCPU
RAM: 32+ GB
Disk: 500+ GB NVMe
```

**Обоснование:**
* Необходимость security scanning для compliance.
* Geo для disaster recovery.
* LDAP integration для enterprise auth.

### Сценарий 3: Enterprise (100+ users, strict compliance)

**Рекомендация:** GitLab EE Ultimate

```bash
# GitLab EE Ultimate (self-hosted)
# - Vulnerability Management
# - Audit events (unlimited)
# - Compliance frameworks
# - 24/7 support
# - Advanced analytics

# Требования
CPU: 16+ vCPU
RAM: 64+ GB
Disk: 1+ TB NVMe
Network: 10 Gbps
```

**Обоснование:**
* Строгие требования compliance (PCI DSS, SOC 2).
* Необходимость 24/7 support.
* Enterprise-grade security features.

### Сценарий 4: Cost Optimization (Mixed approach)

**Стратегия:** GitLab CE + отдельные инструменты

```yaml
# Использование GitLab CE с дополнительными инструментами:

# Вместо built-in Security Dashboard:
# - Snyk / Trivy для vulnerability scanning
# - SonarQube для code quality
# - OWASP ZAP для DAST

# Вместо built-in Dependency Scanning:
# - Dependabot / Renovate для dependency updates
# - Snyk для license compliance

# Вместо Geo:
# - Ручные бэкапы + offsite replication
# - Scripts для disaster recovery

# Итого стоимость:
# GitLab CE: $0
# Snyk: $0–$50/user/month
# SonarQube: $0 (Community) или $150/user/year
# Общая: существенно ниже EE Ultimate
```

**Обоснование:**
* Полный контроль над инструментами.
* Возможность выбора лучших инструментов для каждой задачи.
* Минимизация затрат на лицензии.

### Сценарий 5: Migration path CE → EE

```bash
# 1. Оценка необходимых функций EE
# - Security Dashboard
# - Geo
# - Advanced merge request approvals

# 2. Проверка compatibility
# - Убедиться, что текущая версия GitLab поддерживает EE
# - Проверить PostgreSQL версию

# 3. Backup
sudo gitlab-backup create

# 4. Переключение на EE пакет
# Debian/Ubuntu:
sudo apt install gitlab-ee

# RHEL/CentOS:
sudo yum install gitlab-ee

# Docker:
docker pull gitlab/gitlab-ee:19.0.0

# 5. Ввод лицензии
# Через Admin → Settings → License

# 6. Применение
sudo gitlab-ctl reconfigure
sudo gitlab-ctl restart
```

## Валидация выбора редакции

После выбора редакции проверьте соответствие инфраструктуры и требований:

```bash
# 1. Проверка доступности функций EE
# Omnibus
gitlab-rake gitlab:env:info | grep "Installation Type"

# Docker
docker exec gitlab gitlab-rake gitlab:env:info | grep "Installation Type"

# Helm
kubectl exec -it gitlab-webservice-default-0 -- gitlab-rake gitlab:env:info | grep "Installation Type"

# 2. Проверка лицензии (если используется EE)
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/license" | jq .

# 3. Проверка utilisation seats
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/license" | jq '{active_user_count, max_active_users}'

# 4. Проверка доступности функций
# - Security Dashboard: Admin → Security → Configuration
# - Geo: Admin → Settings → Geo
# - Audit events: Admin → Settings → Audit Events
```

### Критерии готовности

* Выбранная редакция покрывает все обязательные compliance требования.
* Лицензия валидна и количество seats соответствует текущему количеству пользователей.
* Инфраструктура соответствует минимальным требованиям выбранной редакции.
* Команда прошла обучение по особенностям выбранной редакции.

## Операции и команды

### Проверка текущей редакции

```bash
# Omnibus
gitlab-rake gitlab:env:info | grep "Installation Type"

# Docker
docker exec gitlab gitlab-rake gitlab:env:info | grep "Installation Type"

# Helm
kubectl exec -it gitlab-webservice-default-0 -- gitlab-rake gitlab:env:info | grep "Installation Type"
```

### Управление лицензией

```bash
# Просмотр текущей лицензии (Admin → Settings → License)

# Через API
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/license"

# Добавление лицензии
curl --header "PRIVATE-TOKEN: <token>" \
  --request POST \
  --header "Content-Type: application/json" \
  --data '{"license": "BASE64_ENCODED_LICENSE"}' \
  "https://gitlab.example.com/api/v4/license"
```

### Управление пользователями и seats

```bash
# Просмотр количества пользователей
sudo gitlab-rake gitlab:user:list | wc -l

# Просмотр seat utilization
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/license" | jq '.active_user_count'
```

## Типичные ошибки и решения

| Симптом | Причина | Решение |
|:---|:---|:---|
| `License expired` | Истёк срок действия лицензии | Обновите лицензию через Admin → Settings → License |
| `Max active users exceeded` | Превышен лимит пользователей | Приобретите дополнительные seats или удалите неактивных пользователей |
| `Feature not available` | Функция доступна только в EE | Перейдите на EE или используйте альтернативный инструмент |
| `Upgrade to EE failed` | Несовместимая версия | Проверьте upgrade path, обновите до поддерживаемой версии |
| `License file invalid` | Повреждённый файл лицензии | Запросите новый файл лицензии у GitLab |

## Граничные случаи и ограничения

### Расхождения между SaaS и Self-Managed

Некоторые функции доступны только в определённых моделях deployment:
* GitLab Free с ограничением 5 пользователей относится к SaaS-модели; self-hosted GitLab CE не имеет ограничения по пользователям.
* Compute minutes (10 000 в Premium, 50 000 в Ultimate) относятся к SaaS; на self-hosted с собственными runner'ами минуты не ограничиваются тарифом.
* Guest users: в GitLab Free и Premium гостевые пользователи занимают paid seat; в Ultimate — нет.

### Рост beyond текущей редакции

При масштабировании команды может потребоваться переход между редакциями:
* **CE → Premium:** требуется при необходимости Security scanning, LDAP group sync, Geo.
* **Premium → Ultimate:** требуется при необходимости Pipeline execution policies, Compliance frameworks, unlimited audit events, advanced vulnerability management.
* **Миграция лицензии:** не требует переустановки; достаточно переключить пакет и ввести новый лицензионный ключ.

### Смешанные окружения

В крупных организациях могут сосуществовать:
* Self-hosted GitLab EE для разработки.
* GitLab SaaS Free/Premium для внешних контрактёров.
* Изолированные инстансы для air-gapped проектов.

Рекомендации:
* Единый стандарт на редакцию внутри одной команды.
* Документирование причин отклонений от стандарта.
* Централизованное управление лицензиями через procurement team.

### Air-gapped окружения

Для air-gapped развёртываний:
* GitLab CE/EE скачиваются из локального mirror.
* Все зависимости (образа runner'ов, пакеты ОС) также должны быть локально доступны.
* Лицензии EE хранятся в air-gapped сети; обновление требует физический перенос (sneakernet) или VPN.

### Ограничения лицензирования

* **Seat counting:** активные пользователи считаются за 30 дней; неактивные пользователи автоматически освобождают seat.
* **Billing:** GitLab EE billed annually; отмена подписки приводит к потере функций, но данные остаются доступны в CE-режиме.
* **Trial:** trial-версия EE действует 30 дней; после окончания trial инстанс возвращается к функционалу Free/CE.

## Лучшие практики

### Выбор редакции

* **Start small:** начинайте с GitLab CE, переходите на EE по мере роста потребностей.
* **Feature audit:** регулярно аудируйте используемые функции и сравнивайте с EE функционалом.
* **TCO analysis:** оценивайте совокупную стоимость владения (лицензии + инфраструктура + эксплуатация).
* **Trial:** используйте trial-версию EE для оценки перед покупкой.

### Лицензирование

* **Accurate counting:** отслеживайте активных пользователей для планирования лицензий.
* **Bulk licensing:** для enterprise (>100 users) обсуждайте корпоративные тарифы.
* **License management:** назначьте ответственного за управление лицензиями.

### Migration

* **Staging:** всегда тестируйте upgrade CE → EE в staging.
* **Backup:** создавайте полный бэкап перед изменением редакции.
* **Feature validation:** после upgrade проверьте доступность необходимых функций.

### Операционная деятельность (SRE / Sysadmin)

* **Seat audit:** ежемесячно проверяйте utilisation лицензии через API или Admin Area. Автоматизируйте оповещение при приближении к лимиту.
* **License renewal:** назначайте ответственного за renewal за 30–60 дней до истечения. Архивируйте старые лицензионные файлы.
* **Edition lock:** документируйте выбранную редакцию и обоснование в runbook. Изменение редакции должно проходить через Change Management.
* **Feature flag hygiene:** при переходе на EE постепенно внедряйте новые функции через feature flags, а не массово включайте всё сразу.
* **Compliance mapping:** сопоставьте compliance требования (PCI DSS, SOC 2, ISO 27001) с функциями редакции перед покупкой.
* **DR requirements:** если для бизнеса критичен RTO/RPO, выбирайте Premium/Ultimate для доступа к Geo и расширенным возможностям бэкапа.

### Безопасность

* **Edition-specific hardening:** Premium/Ultimate предоставляют дополнительные возможности аудита и контроля доступа. Используйте их.
* **Guest user isolation:** на GitLab Free и Premium гостевые пользователи занимают seat — ограничьте их права через роли.
* **License file protection:** храните лицензионный файл в `gitlab-secrets.json` backup; контролируйте доступ через `chmod 600`.

### Cost optimization

* **GitLab SaaS vs Self-Managed:** оценивайте TCO обеих моделей.
* **Tool consolidation:** оценивайте возможность замены отдельных инструментов на built-in функции GitLab.
* **Cloud vs On-prem:** учитывайте затраты на инфраструктуру и администрирование.

## Дополнительная информация

### Связанные темы

* **[Архитектура GitLab](../Concepts/gitlab_platform_architecture.md)** — общая архитектура и компоненты
* **[Администрирование GitLab в масштабе](./gitlab_administration_at_scale.md)** — распределённые архитектуры
*   **[Установка Self-Hosted GitLab CE](../Tutorials/self_hosted_installation.md)** — практическое руководство
* **[CI/CD Cost Optimization](../Advanced/cicd_cost_optimization.md)** — оптимизация затрат CI/CD

### Внешние ресурсы

* [GitLab Pricing](https://about.gitlab.com/pricing/)
* [GitLab Self-Managed vs SaaS](https://docs.gitlab.com/ee/install/azure/#self-managed-vs-saas)
* [GitLab License FAQ](https://about.gitlab.com/licensing/)
