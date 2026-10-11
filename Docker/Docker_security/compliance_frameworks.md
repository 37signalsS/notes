# Compliance-фреймворки и Docker

**Актуально для:** Docker Engine 29.x; PCI DSS v4.0.1, ISO/IEC 27001:2022, SOC 2 Type II (2026), GDPR, 152-ФЗ, EU CRA (2026). Общая теория аудита и compliance — SSoT в [audit_and_compliance_overview.md](../../Security/audit_and_compliance_overview.md). Данный файл — привязка требований фреймворков к конкретным контролям Docker.

## Определения

**Compliance-фреймворк** — набор требований к ИБ, с которыми организация должна соответствовать (регуляторно или добровольно). Для контейнеров ключевые: PCI DSS (платёжные карты), ISO 27001 (СУИБ), SOC 2 (доверие сервиса), GDPR/152-ФЗ (персональные данные), EU CRA (киберустойчивость ПО).

**CDE (Cardholder Data Environment)** — среда, где обрабатываются платёжные данные. Каждый контейнер в CDE — отдельный объект аудита.

**CIS Benchmark** — набор проверок конфигурации Docker против отраслевых бест-практик; де-факто базовая линия для аудита контейнеров. Актуальная версия для Docker — v1.6.0 (2026).

**SBOM** — перечень компонентов образа; требуется EU CRA и рекомендуется PCI DSS для управления уязвимостями.

**Attestation** — криптографическое подтверждение происхождения и целостности артефакта (cosign attestations, SLSA).

**Continuous Compliance** — интеграция проверок соответствия в CI/CD-пайплайн с автоматическим evidence collection; позволяет обнаруживать нарушения до production.

## Предварительные требования

- **Docker Engine:** 29.x (актуальный релиз 29.8.x на октябрь 2026). Docker 28.x и ранее достигли EOL (май 2026) и не получают исправлений безопасности.
- **ОС:** Linux с ядром 5.4+ (cgroups v2, User Namespaces, eBPF). RHEL/CentOS 8+, Debian 11+, Ubuntu 20.04+.
- **Инструменты:**
  - `docker-bench-security` (образ на основе CIS Docker Benchmark v1.6.0)
  - `trivy` (сканирование образов)
  - `syft` (генерация SBOM в SPDX/CycloneDX)
  - `cosign` (подпись и attestations)
  - `auditd` (аудит событий хоста)
  - `falco` или `tetragon` (runtime security)
  - `jq` (парсинг JSON-вывода)
- **Права:** Для управления демоном — `root` или группа `docker`. В production — предпочтителен Rootless Docker.
- **Сеть:** Порт 2376 (mTLS) или 22 (SSH) для удалённого управления. Порт 2375 (TCP без TLS) категорически запрещён.

## Базовые концепции

### Почему контейнеры не создают исключений

Фреймворки требуют контроля **данных и процессов**, а не технологий. Контейнер, обрабатывающий карты или персональные данные, подпадает под те же требования, что и виртуальная машина: сегментация сети, минимальные привилегии, логирование, управление уязвимостями. Разница — в инструментах: вместо host-based IPS — Falco, вместо agent-сканера — Trivy в CI, вместо ручного харденинга — CIS Benchmark.

### Continuous Compliance и Docker

Непрерывный комплаенс (Continuous Compliance) — интеграция проверок соответствия в каждый этап CI/CD. Для Docker это означает:

- **Scan on build:** Trivy gate на CRITICAL уязвимости при `docker build`.
- **Policy as Code:** OPA Gatekeeper или Kyverno проверяют образы на подпись, SBOM и наличие banned base images перед deploy.
- **Automated evidence collection:** вывод `docker-bench-security`, результаты сканирования и SBOM сохраняются как артефакты релиза с криптографическим хэшем.
- **Drift detection:** сравнение фактической конфигурации демона (`daemon.json`, запущенные контейнеры) с политикой; алерт при отклонениях.

Цель — перейти от ежегодного аудита к автоматически собираемым доказательствам, которые аудитор проверяет выборкой, а не вручную.

### Карта требований к контролям Docker

| Требование | PCI DSS v4.0.1 | ISO 27001:2022 | SOC 2 (2026) | GDPR/152-ФЗ | EU CRA |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Сегментация сети | Req. 1 | A.8.20 | CC6.1 | — | — |
| Безопасная конфигурация | Req. 2 | A.8.9 | CC6.1 | Art. 32 | Art. 3 |
| Управление секретами | Req. 3 | A.8.24 | CC6.1 | Art. 32 | — |
| Управление уязвимостями | Req. 6 | A.8.8 | CC7.1 | Art. 32 | Art. 11 |
| Логирование и мониторинг | Req. 10 | A.8.15 | CC7.2/CC7.3 | Art. 32 | — |
| Тестирование безопасности | Req. 11 | A.8.28 | CC4.1 | — | Art. 9 |
| Supply chain / SBOM | Req. 6.3 | A.5.19 | CC4.1 | — | Art. 11 |

**Примечания:**
- ISO 27001:2022 перешла на структуру из 93 контролей (вместо 114 в версии 2013). Контроли A.8.x относятся к технической реализации ИБ.
- SOC 2 (2026) усилил фокус на supply chain (CC4.1 — логирование всех изменений артефактов) и распределённых системах (CC7.x — мониторинг в реальном времени).
- EU CRA введён в 2026 году как обязательный для цифровых продуктов, поставляемых в ЕС. Арт. 11 — SBOM и процесс обработки уязвимостей; Арт. 3 — безопасный дизайн.

## Практические сценарии

### Сценарий 1: PCI DSS v4.0.1 в Docker-окружении

**Req. 1 — сегментация:** CDE-контейнеры в отдельных bridge-сетях, `icc: false`, egress-белый список, DOCKER-USER-правила. Конфиги — в [network_security.md](./network_security.md) и [docker_network_policies.md](../Docker_network/docker_network_policies.md).

**Req. 2 — безопасная конфигурация:** CIS Benchmark v1.6.0 как базовая линия:

```bash
# Запуск docker-bench-security (образ содержит актуальный CIS Benchmark)
docker run --rm --net host --pid host --userns host --cap-add audit_control \
  -e DOCKER_CONTENT_TRUST=1 -v /var/lib:/var/lib \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /usr/lib/systemd:/usr/lib/systemd -v /etc:/etc \
  --label docker_bench_security docker/docker-bench-security
# → [WARN] 2.11  Ensure the base device size is not changed until needed
```

**Валидация:**
```bash
docker run --rm docker/docker-bench-security --check 2.1,2.11,2.12
# → PASS: 2.1  Ensure that the container root filesystem is mounted as read only
# → WARN: 2.11 Ensure the base device size is not changed until needed
```

**Req. 3 — секреты:** не через ENV; Docker secrets или Vault. Практики — в [secrets_management.md](./secrets_management.md).

**Req. 6 — уязвимости:** сканирование образов в CI, fail на CRITICAL, SBOM. — в [vulnerability_scanning.md](./vulnerability_scanning.md) и [docker_sbom.md](./docker_sbom.md).

**Req. 10 — логирование:** json-file драйвер с ротацией, централизация в SIEM, аудит демона через auditd. — в [docker_log_rotation.md](../Docker_logs/docker_log_rotation.md) и [auditd](../../Linux/SystemAdministration/Logging/auditd.md).

**Req. 11 — тестирование:** пентест окружения, проверка escape-векторов (CVE-каталог — в [container_escape_cves.md](./container_escape_cves.md)).

### Сценарий 2: ISO 27001 / SOC 2 — доказательства

Аудитору нужны **артефакты**, а не утверждения. Для SOC 2 attestation period (обычно 12 месяцев) требуется непрерывный сбор evidence:

| Контроль | Артефакт | Источник |
| :--- | :--- | :--- |
| Сканирование образов | Логи CI с результатами Trivy | [vulnerability_scanning.md](./vulnerability_scanning.md) |
| Конфигурация демона | `daemon.json` + вывод CIS Benchmark | [host_daemon_hardening.md](./host_daemon_hardening.md) |
| Мониторинг | Правила Falco, алерты SIEM | [runtime_monitoring.md](./runtime_monitoring.md) |
| Управление секретами | Политика ротации, вывод `docker secret ls` | [secrets_management.md](./secrets_management.md) |
| Реагирование | Runbook инцидентов, логи расследований | [incident_response.md](./incident_response.md) |
| Подписи образов | Cosign-подписи и SBOM как артефакты релиза | [image_signature_and_verification.md](./image_signature_and_verification.md) |

### Сценарий 3: GDPR / 152-ФЗ — персональные данные в контейнерах

- **Art. 32 (GDPR) / ст. 19 (152-ФЗ):** шифрование ПДн в контейнерах — тома с `:Z` (SELinux) или зашифрованные volumes (LUKS); секреты не в ENV.
- **Минимизация:** образы без ПДн (не включать дампы БД в слои — см. [Dockerfile security](../Dockerfile/Docker_best_practices/security.md)); удаление ПДн из слоёв при утечке в историю сборки.
- **Аудит доступа:** кто запускал `docker exec` в контейнере с ПДн — через auditd-правила на демон и сокет.
- **Удаление (right to erasure):** `docker volume rm` + перезапись тома (`shred` или `dd`); учёт реплик в registry.
- **Retention:** логи аудита хранятся минимум 1 год (GDPR Art. 5 — принцип подотчётности; 152-ФЗ — не менее 1 года для ИСПДн).

### Сценарий 4: EU CRA (Cyber Resilience Act)

CRA требует от производителей ПО: SBOM (Art. 11), процесс обработки уязвимостей (Art. 11), безопасный дизайн (Art. 3), документацию по безопасности. Для Docker-артефактов:

1. SBOM в SPDX/CycloneDX к каждому релизу: `syft my-app:latest -o spdx-json`. Хранить минимум 12 месяцев после вывода продукта из эксплуатации (Art. 14).
2. Подписи и attestations: cosign sign/attest (SLSA-уровень provenance).
3. Процесс: SLA на патчинг CVE (critical — 24ч, high — 72ч), канал раскрытия (security advisory).
4. Версии: пининг по digest, политика EOL базовых образов.
5. NIST SSDF: соблюдение рекомендаций по безопасной разработке (SLSA, dependency review, provenance).
6. CDXA: поддержка обмена SBOM/VEX данными с потребителями.

Supply-chain практики — в [Security/Supply_Chain_Security](../../Security/Supply_Chain_Security/).

### Сценарий 5: SOC 2 Type II — attestation period и evidence automation

SOC 2 Type II требует доказательств эффективности контролей за период (обычно 12 месяцев). Для Docker-инфраструктуры:

- **Attestation period coverage:** логи должны покрывать весь период (не менее 1 года). Для `docker events` и `auditd` — экспорт в SIEM с retention ≥ 12 месяцев.
- **Automated evidence collection:** каждый CI/CD run генерирует пакет артефактов (CIS Benchmark output, Trivy scan, SBOM, cosign signatures) и хранит в артефакт-реестре с дайджестом.
- **Drift detection:** nightly job сравнивает `daemon.json` и политики запуска контейнеров с заявленными; алерт при отклонении.
- **Инструменты:** Drift as Code — OpenPolicyAgent или Kyverno для проверки фактического состояния против политики.

### Сценарий 6: FIPS 140-2 — криптографические модули в Docker

Docker Engine CE **не имеет** FIPS-валидированного криптомодуля. Валидированный модуль (Certificate #3304, FIPS 140-2 Level 1) есть только в Mirantis Container Runtime (ex Docker Engine Enterprise).

Для Docker CE альтернативы:
1. **FIPS-enabled хост:** включение FIPS mode в ядре (`fips=1`, проверка `cat /proc/sys/crypto/fips_enabled` → `1`).
2. **UBI base images:** использование Red Hat UBI с FIPS-валидированным OpenSSL.
3. **Mirantis Container Runtime (MCR):** полная FIPS-валидация для TLS сокета демона, Swarm mTLS, overlay-сетей.
4. **Go boringcrypto:** сборка собственных инструментов с FIPS-валидированной криптографией.

Подробно — в [fips_compliance.md](./fips_compliance.md).

### Сценарий 7: Continuous Compliance pipeline

Автоматизация проверок соответствия в CI/CD:

```yaml
# Пример этапа в pipeline (GitLab CI / GitHub Actions)
compliance_gate:
  stage: test
  image: aquasec/trivy:latest
  script:
    # Сканирование образов
    - trivy image --severity CRITICAL --exit-code 1 my-registry.com/app:$CI_COMMIT_SHA
    # Генерация SBOM
    - syft my-registry.com/app:$CI_COMMIT_SHA -o spdx-json > sbom.spdx.json
    # Проверка подписи
    - cosign verify --key cosign.pub my-registry.com/app:$CI_COMMIT_SHA
  artifacts:
    paths:
      - sbom.spdx.json
      - trivy-report.json
    expire_in: 12 months
```

**Policy as Code:**
- **OPA Gatekeeper / Kyverno** проверяют, что образы имеют валидную подпись и SBOM.
- **CIS Benchmark** запускается nightly и сравнивает фактическую конфигурацию с политикой.
- **Falco** алертит на нарушения политик (например, запуск привилегированного контейнера в production).

## Устранение неполадок

| Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| Аудитор не принимает «у нас Docker» как контроль | Нет артефактов | Собрать вывод CIS Benchmark, логи сканирования, политики — по таблице в сценарии 2 |
| CIS Benchmark: WARN по сокету | `/var/run/docker.sock` доступен широко | `ls -l /var/run/docker.sock` → `root:docker 660`; ограничить группу `docker`; в rootless использовать `DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock` |
| Нет доказательств сканирования | Сканирование не в CI | Добавить Trivy-шаг в pipeline с fail на CRITICAL; артефакт хранить ≥ 12 месяцев |
| ПДн в слоях образа | COPY дампов/конфигов с секретами | Пересобрать без секретов; использовать multi-stage build; ротация скомпрометированных секретов; проверить `docker history` |
| Нет SBOM | Не генерировался | `syft`/`trivy sbom` в CI; сохранять как артефакт релиза; для EU CRA хранить ≥ 12 месяцев после EOL |
| `docker-bench-security` падает на `--userns host` | Rootless mode или userns-remap активны | В CI запускать без `--userns host`; на production-хостах проверять политику вручную или через Ansible |
| Attestation period покрывает не весь год | Логи удаляются раньше | Настроить retention в SIEM ≥ 12 месяцев; для PCI DSS — hot storage 3 месяца, warm — 9 месяцев |
| FIPS audit fails | Docker Engine CE без FIPS-модуля | Перейти на Mirantis Container Runtime (MCR) или использовать FIPS-enabled хост + UBI base images |
| Policy as Code не применяется | Kyverno/OPA не установлен или политика не активна | `kubectl get clusterpolicy`; проверить webhook; убедиться, что admission-регистрация прошла |
| SBOM в неправильном формате | EU CRA требует SPDX или CycloneDX | Генерировать напрямую (`syft -o spdx-json`); избегать конвертации для compliance-документов |
| Сегментация CDE не проходит аудит | Есть контейнеры с картами в общей сети | Проверить `docker network inspect`; DOCKER-USER-правила; `docker ps --filter label=stage=prod` |
| Подпись образа отсутствует | Cosign не настроен или ключ утерян | `cosign generate-key-pair`; добавить шаг подписи в CI; для Docker Content Trust — `DOCKER_CONTENT_TRUST=1` |

## Лучшие практики

1. **CIS Benchmark — минимум.** Прогонять регулярно (еженедельно), WARN-ы трактовать как техдолг. Использовать актуальный образ `docker/docker-bench-security` (v1.6.0 на 2026 год).
2. **Артефакты важнее настроек.** Каждый контроль должен оставлять доказательство: лог, отчёт, конфиг в Git. Для SOC 2 attestation period — артефакты хранить ≥ 12 месяцев в SIEM/артефакт-реестре.
3. **Сканирование — gate в CI.** Не «проверим перед релизом», а fail build на CRITICAL без fixed-версии. Интегрировать Trivy в каждый `docker build`.
4. **Секреты — только менеджеры.** ENV-переменные не проходят аудит PCI/GDPR. Использовать Docker Secrets, Vault или BuildKit `--secret`.
5. **Сегментация CDE.** Контейнеры с картами/ПДн — отдельные сети, egress-белый список, мониторинг Falco/Tetragon.
6. **SBOM и подписи** к каждому релизу — требование EU CRA, ожидание SOC 2. Форматы: SPDX или CycloneDX. Хранить ≥ 12 месяцев после EOL продукта.
7. **Runbook инцидентов** — требование всех фреймворков; шаблон — в [incident_response.md](./incident_response.md).
8. **Continuous Compliance.** Внедрить Policy as Code (Kyverno/OPA) для превентивной проверки образов и конфигурации. Nightly drift detection для `daemon.json`.
9. **FIPS-совместимость.** Если требуется FIPS 140-2 — использовать Mirantis Container Runtime (MCR) или FIPS-enabled хост + UBI base images. Docker Engine CE не имеет FIPS-валидированного криптомодуля.
10. **Только доверенные base images.** Блокировать `:latest` и неверифицированные образы в CI. Использовать digest pinning (`image@sha256:...`).
11. **Rootless Docker — стандарт для production.** Запуск демона от непривилегированного пользователя предотвращает получение root на хосте при компрометации контейнера.
12. **Аудит по умолчанию.** Включите `auditd` для критических файлов (`/var/run/docker.sock`, `daemon.json`, бинарники docker) и мониторинг `docker events` в централизованное хранилище.
13. **Evidence immutability.** Артефакты compliance (сканы, SBOM, подписи) должны быть неизменяемыми: хранение в WORM-хранилище или реестре с ревизиями (Docker Hub Immutable Tag, Harbor).
14. **Attestation coverage.** Для SOC 2 — evidence должен покрывать весь attestation period (12 месяцев). Проверяйте retention политики в SIEM и артефакт-реестре.

## Дополнительная информация

### Граничные случаи и ограничения

- **Rootless Docker и compliance:** auditd-правила должны покрывать `$XDG_RUNTIME_DIR/docker.sock`, а не только `/var/run/docker.sock`. Falco может требовать отдельной конфигурации для rootless-сокетов.
- **Multi-tenancy и PCI DSS:** в shared Docker-хостах группа `docker` даёт root-доступ к хосту; для CDE требуются отдельные хосты или Kata Containers для аппаратной изоляции.
- **User Namespaces и bind mounts:** `userns-remap` меняет UID/GID, что ломает права на bind-mounted тома. Для compliance критичных данных используйте Docker Volumes вместо Bind Mount.
- **Overlay2 и userns-remap:** на некоторых ядрах overlay2 не поддерживается с `userns-remap`. Альтернативы: `fuse-overlayfs` или `vfs`.
- **Registry retention:** для EU CRA SBOM нужно хранить ≥ 12 месяцев после EOL. Убедитесь, что registry (Harbor, GHCR) не настроен на автоматическое удаление артефактов раньше.
- **CIS Benchmark и кастомные драйверы:** docker-bench-security проверяет стандартные параметры; кастомные storage drivers (`zfs`, `btrfs`) требуют ручной проверки соответствующих контролей.
- **Log rotation и PCI DSS:** `json-file` драйвер по умолчанию ротирует на 100MB без лимита файлов; для PCI DSS требуется настроить `max-file` и `max-size` и centralized logging в SIEM.
- **SBOM и transitive dependencies:** `syft`/`trivy` могут не детектировать зависимости, собранные из исходников без менеджера пакетов. Для compliance проверяйте reproducibility сборки и использование distroless/chainguard образов.

**Связанные документы:**

- [Обзор аудита и compliance](../../Security/audit_and_compliance_overview.md) — SSoT: PCI DSS, ISO 27001, SOC 2, GDPR, 152-ФЗ, EU CRA.
- [Docker Bench CIS](./docker_bench_cis.md) — проверки конфигурации.
- [Сканирование уязвимостей](./vulnerability_scanning.md), [SBOM](./docker_sbom.md).
- [Управление секретами](./secrets_management.md), [сетевая безопасность](./network_security.md).
- [Реагирование на инциденты](./incident_response.md).
- [Supply Chain Security](../../Security/Supply_Chain_Security/) — SLSA, provenance, attestations.

**Внешние ресурсы:**

- [PCI DSS v4.0.1](https://www.pcisecuritystandards.org/) — требования к CDE.
- [CIS Docker Benchmark](https://www.cisecurity.org/benchmark/docker) — конфигурационные контрольные точки.
- [EU CRA](https://cyberresilienceact.eu/) — требования к ПО с цифровыми элементами.

**Инструменты:** `docker/docker-bench-security`, `trivy`, `syft`, `cosign`, Falco, SIEM.
